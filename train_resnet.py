#!/usr/bin/env python

import argparse
import os
from datetime import datetime
from shutil import copyfile

import numpy as np
import tensorflow as tf
from tensorflow.keras.datasets import cifar10

from src.resnet import resnet_50

def train(epochs, batch_size, input_size, quantized_training, asymetric_conv, depthwise_conv, folder_name, early_stopping):

    (X_train, Y_train), _ = cifar10.load_data()


    validation_split = 0.1
    X_train = X_train[:-int(X_train.shape[0]*validation_split)]
    Y_train = Y_train[:-int(Y_train.shape[0]*validation_split)]
    X_val = X_train[-int(X_train.shape[0]*validation_split):]
    Y_val = Y_train[-int(Y_train.shape[0]*validation_split):]

    Y_train = tf.keras.utils.to_categorical(Y_train, 10)
    Y_val = tf.keras.utils.to_categorical(Y_val, 10)

    # Rescale
    X_train = X_train/255.
    X_val = X_val/255. 

    ds_train = tf.data.Dataset.from_tensor_slices((X_train, Y_train)).shuffle(100).batch(batch_size).cache().prefetch(tf.data.experimental.AUTOTUNE)
    ds_val = tf.data.Dataset.from_tensor_slices((X_val, Y_val)).batch(batch_size).cache().prefetch(tf.data.experimental.AUTOTUNE)

    model_dir = 'models/' + folder_name
    if not os.path.isdir(model_dir):
        os.makedirs(model_dir)

    log_dir = "logs/fit/" + folder_name
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)

    checkpoint_dir = model_dir + '/checkpoints/'
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)

    copyfile('./train_resnet.py', model_dir + '/train_resnet.py')

    tf.keras.backend.clear_session()
    def get_compiled_model():
        model_input=tf.keras.layers.Input(input_size)
        ## Preprocessing Layers Here ##
        model_input = tf.keras.layers.experimental.preprocessing.RandomFlip("horizontal")(model_input)
        model_input = tf.keras.layers.experimental.preprocessing.RandomRotation(0.1)(model_input)
        model_input = tf.keras.layers.experimental.preprocessing.RandomZoom(0.1)(model_input)
        ###############################
        model = resnet_50(model_input, spatial_sep_conv=asymetric_conv, depthwise_sep_conv=depthwise_conv)
        if quantized_training:
            import tensorflow_model_optimization as tfmot
            def apply_quantization(layer):
                if isinstance(layer, tf.keras.layers.Conv2D):
                    return tfmot.quantization.keras.quantize_annotate_layer(layer)
                if isinstance(layer, tf.keras.layers.SeparableConv2D):
                    return tfmot.quantization.keras.quantize_annotate_layer(layer)
                if isinstance(layer, tf.keras.layers.Dense):
                    return tfmot.quantization.keras.quantize_annotate_layer(layer)
                return layer
            model = tf.keras.models.clone_model(model, clone_function=apply_quantization)
            with tfmot.quantization.keras.quantize_scope({}):
                # Use `quantize_apply` to actually make the model quantization aware.
                model = tfmot.quantization.keras.quantize_apply(model)
        optimizer = tf.keras.optimizers.Adam()
        model.compile(
            loss=tf.keras.losses.categorical_crossentropy,
            optimizer=optimizer,
            metrics=['accuracy']
        )
        return model

    def make_or_restore_model():
        # Either restore the latest model, or create a fresh one
        # if there is no checkpoint available.
        checkpoints = [checkpoint_dir + name for name in os.listdir(checkpoint_dir)]
        if checkpoints:
            latest_checkpoint = max(checkpoints, key=os.path.getctime)
            print("Restoring from", latest_checkpoint)
            return tf.keras.models.load_model(latest_checkpoint)
        print("Creating a new model")
        return get_compiled_model()

    model = make_or_restore_model()

    callbacks = [
        tf.keras.callbacks.TensorBoard(
            log_dir=log_dir, 
            histogram_freq=5,
            profile_batch=0
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=checkpoint_dir + 'model_{epoch}',
            save_freq='epoch',
            period=10
        )
    ]
    if early_stopping:
        callbacks.append(
            tf.keras.callbacks.EarlyStopping(
                monitor='val_loss',
                min_delta=0.005,
                patience=10,
                verbose=1,
                restore_best_weights=True
            )
        )

    model.summary()

    model.fit(
        ds_train,
        epochs=epochs,
        validation_data=ds_val,
        callbacks=callbacks
    )

    model.save(model_dir + '/model')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--folder_name', default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument('-q', '--quantized_training', action='store_true', default=False)
    parser.add_argument('-a', '--asymetric', action='store_true', default=False)
    parser.add_argument('-d', '--depthwise', action='store_true', default=False)
    parser.add_argument('-e', '--epochs', type=int, default=50)
    parser.add_argument('-b', '--batch_size', type=int, default=32)
    parser.add_argument('-i', '--input_size', type=int, default=32)
    parser.add_argument('--early_stopping', action='store_true', default=False)
    args = parser.parse_args()


    epochs = args.epochs
    batch_size = args.batch_size
    input_size = (args.input_size, args.input_size, 3)
    quantized_training = args.quantized_training
    asymetric_conv = args.asymetric
    depthwise_conv = args.depthwise
    folder_name = args.folder_name
    early_stopping = args.early_stopping

    train(epochs, batch_size, input_size, quantized_training, asymetric_conv, depthwise_conv, folder_name, early_stopping)